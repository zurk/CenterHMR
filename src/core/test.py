from pathlib import Path

from tqdm import tqdm

from utils.multiprocess import *


class Demo(Base):
    def __init__(self):
        super(Demo, self).__init__()
        self.set_up_smplx()
        self._build_model()
        self.generator.eval()
        self.save_mesh = args.save_mesh
        self.save_centermap = args.save_centermap
        self.save_dict_results = args.save_dict_results
        self.demo_dir = os.path.join(config.project_dir, 'demo')
        self.vis_size = [1024, 1024, 3]
        if not args.webcam and '-1' not in self.gpu:
            self.visualizer = Visualizer(
                model_type=self.model_type,
                resolution=self.vis_size,
                input_size=self.input_size,
                with_renderer=True,
            )
        else:
            self.save_visualization_on_img = False
        print('Initialization finished!')

    def run(self, image_folder):
        print('Processing {}'.format(image_folder))
        if self.output_dir is not None:
            test_save_dir = self.output_dir
        else:
            test_save_dir = image_folder + '_results'
        os.makedirs(test_save_dir, exist_ok=True)
        if '-1' not in self.gpu:
            self.visualizer.result_img_dir = test_save_dir
        counter = Time_counter(thresh=1)

        exclude = set([
            file.relative_to(test_save_dir).with_suffix('')
            for file in Path(test_save_dir).glob('**/*')
            if file.is_file()
        ])

        loader_val = self._create_single_data_loader(
            dataset='internet',
            train_flag=False,
            image_folder=image_folder,
            exclude=exclude,
        )
        counter.start()
        with torch.no_grad():
            for test_iter, data_3d in enumerate(tqdm(loader_val, total=len(loader_val))):
                outputs, centermaps, heatmap_AEs, data_3d_new, reorganize_idx = self.net_forward(
                    data_3d, self.generator, mode='test'
                )
                if 'params' not in outputs:
                    print(f"No params in outputs for {data_3d['imgpath']} iter {test_iter}")
                    continue
                counter.count()
                if self.save_dict_results:
                    self.reorganize_results(
                        outputs, data_3d['imgpath'], reorganize_idx, test_save_dir, image_folder
                    )
                if not self.save_centermap:
                    centermaps = None
                if outputs['success_flag'] and self.save_visualization_on_img:
                    vis_eval_results = self.visualizer.visulize_result_onorg(
                        outputs['verts'],
                        outputs['verts_camed'],
                        data_3d_new,
                        reorganize_idx,
                        centermaps=centermaps,
                        save_img=True,
                    )  #
                # counter.fps()
                if self.save_mesh:
                    vids_org = np.unique(reorganize_idx)
                    for idx, vid in enumerate(vids_org):
                        verts_vids = np.where(reorganize_idx == vid)[0]
                        img_path = data_3d['imgpath'][verts_vids[0]]
                        obj_name = (
                            (test_save_dir + '/{}'.format(os.path.basename(img_path)))
                            .replace('.jpg', '.obj')
                            .replace('.png', '.obj')
                        )
                        for subject_idx, batch_idx in enumerate(verts_vids):
                            save_obj(
                                outputs['verts'][batch_idx]
                                .detach()
                                .cpu()
                                .numpy()
                                .astype(np.float16),
                                self.smplx.faces_tensor.detach().cpu().numpy(),
                                obj_name.replace('.obj', '_{}.obj'.format(subject_idx)),
                            )
                counter.start()

    def reorganize_results(self, outputs, img_paths, reorganize_idx, test_save_dir, image_folder):
        results = {}
        cam_results = outputs['params']['cam'].detach().cpu().numpy().astype(np.float16)
        smpl_pose_results = (
            torch.cat([outputs['params']['global_orient'], outputs['params']['body_pose']], 1)
            .detach()
            .cpu()
            .numpy()
            .astype(np.float16)
        )
        smpl_shape_results = outputs['params']['betas'].detach().cpu().numpy().astype(np.float16)
        kp3d_smpl24_results = outputs['j3d_smpl24'].detach().cpu().numpy().astype(np.float16)
        kp3d_spin24_results = outputs['j3d_spin24'].detach().cpu().numpy().astype(np.float16)
        kp3d_op25_results = outputs['j3d_op25'].detach().cpu().numpy().astype(np.float16)
        verts_results = outputs['verts'].detach().cpu().numpy().astype(np.float16)

        vids_org = np.unique(reorganize_idx)
        for idx, vid in enumerate(vids_org):
            verts_vids = np.where(reorganize_idx == vid)[0]
            img_path = img_paths[verts_vids[0]]
            results[img_path] = [{} for idx in range(len(verts_vids))]
            for subject_idx, batch_idx in enumerate(verts_vids):
                results[img_path][subject_idx]['cam'] = cam_results[batch_idx]
                results[img_path][subject_idx]['pose'] = smpl_pose_results[batch_idx]
                results[img_path][subject_idx]['betas'] = smpl_shape_results[batch_idx]
                results[img_path][subject_idx]['j3d_smpl24'] = kp3d_smpl24_results[batch_idx]
                results[img_path][subject_idx]['j3d_spin24'] = kp3d_spin24_results[batch_idx]
                results[img_path][subject_idx]['j3d_op25'] = kp3d_op25_results[batch_idx]
                results[img_path][subject_idx]['verts'] = verts_results[batch_idx]
                results[img_path][subject_idx]['img_path'] = Path(img_path).relative_to(image_folder)

        for img_path, result_dict in results.items():
            name = Path(test_save_dir) / Path(img_path).relative_to(image_folder)
            name = name.with_suffix('.npz')
            name.parent.mkdir(exist_ok=True, parents=True)
            # get the results: np.load('/path/to/person_overlap.npz',allow_pickle=True)['results'][()]
            np.savez(name, results=result_dict)

    def single_image_forward(self, image):
        image_size = image.shape[:2][::-1]
        image_org = Image.fromarray(image)

        resized_image_size = (
            float(self.input_size) / max(image_size) * np.array(image_size) // 2 * 2
        ).astype(np.int)[::-1]
        padding = tuple((self.input_size - resized_image_size)[::-1] // 2)
        transform = torchvision.transforms.Compose(
            [
                torchvision.transforms.Resize([*resized_image_size], interpolation=3),
                torchvision.transforms.Pad(padding, fill=0, padding_mode='constant'),
            ]
        )
        image = torch.from_numpy(np.array(transform(image_org))).unsqueeze(0).contiguous().float()
        if '-1' not in self.gpu:
            image = image.cuda()
        outputs, centermaps, heatmap_AEs, _, reorganize_idx = self.net_forward(
            None, self.generator, image, mode='test'
        )
        outputs.update({'input_image': image, 'reorganize_idx': reorganize_idx})
        return outputs

    def process_video(self, video_file_path=None):

        import keyboard
        from utils.demo_utils import OpenCVCapture, frames2video

        capture = OpenCVCapture(video_file_path)
        video_length = int(capture.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        result_frames = []
        for frame_id in range(video_length):
            print('Processing video {}/{}'.format(frame_id, video_length))
            frame = capture.read()
            with torch.no_grad():
                outputs = self.single_image_forward(frame[:, :, ::-1])
            vis_dict = {'image_org': outputs['input_image'].cpu()}
            vis_eval_results = self.visualizer.visulize_result_onorg(
                outputs['verts'],
                outputs['verts_camed'],
                vis_dict,
                reorganize_idx=outputs['reorganize_idx'],
            )
            result_frames.append(vis_eval_results[0])
        video_save_name = video_file_path.replace('.mp4', '_results.mp4')
        print('Writing results to {}'.format(video_save_name))
        frames2video(result_frames, video_save_name, fps=30)

    def webcam_run_local(self, video_file_path=None):
        '''
        20.9 FPS of forward prop. on 1070Ti
        '''
        print('run on local')
        import keyboard
        from utils.demo_utils import OpenCVCapture, Open3d_visualizer, Image_Reader

        capture = OpenCVCapture(video_file_path)
        visualizer = Open3d_visualizer()
        print('Initialization is down')

        # Warm-up
        for i in range(10):
            self.single_image_forward(np.zeros((512, 512, 3)).astype(np.uint8))
        counter = Time_counter(thresh=1)
        while True:
            start_time_perframe = time.time()
            frame = capture.read()
            if frame is None:
                continue

            counter.start()
            with torch.no_grad():
                outputs = self.single_image_forward(frame)
            counter.count()
            counter.fps()

            if outputs is not None and outputs['success_flag']:
                if args.show_single:
                    verts = outputs['verts'].cpu().numpy()
                    verts = verts * 50 + np.array([0, 0, 100])
                    break_flag = visualizer.run(verts[0], frame)
                else:
                    verts = outputs['verts_camed'].cpu().numpy()
                    verts = verts * 50 + np.array([0, 0, 100])
                    break_flag = visualizer.run_multiperson(verts, frame)
                if break_flag:
                    break

    def webcam_run_remote(self):
        print('run on remote')
        from utils.remote_server_utils import Server_port_receiver

        capture = Server_port_receiver()

        while True:
            frame = capture.receive()
            if isinstance(frame, list):
                continue
            with torch.no_grad():
                outputs = self.single_image_forward(frame)
            if outputs is not None:
                verts = outputs['verts'][0].cpu().numpy()
                verts = verts * 50 + np.array([0, 0, 100])
                capture.send(verts)
            else:
                capture.send(['failed'])


class Time_counter:
    def __init__(self, thresh=0.1):
        self.thresh = thresh
        self.runtime = 0
        self.frame_num = 0

    def start(self):
        self.start_time = time.time()

    def count(self):
        time_cost = time.time() - self.start_time
        if time_cost < self.thresh:
            self.runtime += time_cost
            self.frame_num += 1
        self.start()

    def fps(self):
        print('average per-frame runtime:', self.runtime / self.frame_num)
        print('FPS: {}, not including visualization time. '.format(self.frame_num / self.runtime))

    def reset(self):
        self.runtime = 0
        self.frame_num = 0


def main():
    demo = Demo()
    print('Start CneterHMR')
    if args.webcam:
        print('Running on webcam demo')
        if args.run_on_remote_server:
            demo.webcam_run_remote()
        else:
            demo.webcam_run_local()
    elif args.video_or_frame:
        print('Running on video ', args.input_video_path)
        demo.process_video(args.input_video_path)
    elif args.data:
        for data_config in args.data:
            demo_image_folder = data_config['demo_image_folder']
            demo.output_dir = data_config['output_dir']
            demo.run(demo_image_folder)
    else:
        demo_image_folder = args.demo_image_folder
        if not os.path.exists(demo_image_folder):
            print('run the code on demo images')
            demo_image_folder = os.path.join(demo.demo_dir, 'images')
        demo.run(demo_image_folder)


if __name__ == '__main__':

    main()
